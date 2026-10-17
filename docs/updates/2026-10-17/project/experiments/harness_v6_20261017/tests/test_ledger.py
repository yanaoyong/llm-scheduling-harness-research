from copy import deepcopy
import random
import pytest
from harness_v6.ledger import ledger_from_scratch, ledger_apply
from harness_v6.audit_ledger import reconcile


def op(oid='a', **kw):
    return dict(operation_id=oid, lot_id=oid, step=1, visit=1, family='F', eligible_machines=kw.pop('eligible_machines', [1, 2]),
                release_time=0, conditional=False, predecessor_ids=[], batch_key=['P', 1, 'S'],
                batch_min=1, batch_max=3, setup='A', **kw)


def fixture():
    return {'time': 10, 'operations': [op()], 'machines': [
        {'machine': i, 'family': 'F', 'currently_busy': False, 'currently_down': False,
         'available_at': 10, 'min_left': 0, 'min_setup': ''} for i in (1, 2)]}, {'created_at': 0, 'tasks': [], 'holds': []}


def task(oid='a', mid=2, **kw):
    return dict(id='t', machine=mid, operation_ids=[oid], lot_ids=[oid], steps=[1], visits=[1], **kw)


def checked(p, plan, receipts=None):
    l = ledger_from_scratch(p, plan, receipts)
    assert reconcile(l.metrics(), p, plan, receipts)['ok']
    return l


def test_cross_machine_reservation_and_age():
    p, plan = fixture(); plan['tasks'] = [task(not_before=30)]
    l = checked(p, plan)
    assert l.metrics()['avoidable_idle'] == 0
    assert l.metrics()['assigned_not_started_age'] == {'a': 10}
    assert l.metrics()['reserved_but_earlier_startable'][0]['potential_idle_seconds'] == 20
    assert l.rows()['a']['state'] == 'reserved_not_started'


@pytest.mark.parametrize('constraint', ['batch_min', 'dedication', 'min_run', 'conditional', 'uncertain', 'busy', 'down', 'predecessor'])
def test_constraints(constraint):
    p, plan = fixture()
    if constraint == 'batch_min': p['operations'][0]['batch_min'] = 2
    if constraint == 'dedication': p['operations'][0]['eligible_machines'] = [3]
    if constraint == 'min_run':
        for m in p['machines']: m.update(min_left=1, min_setup='B')
    if constraint == 'conditional': p['operations'][0]['conditional'] = True
    if constraint == 'uncertain': p['operations'][0]['qualification_uncertain'] = True
    if constraint in ('busy', 'down'):
        for m in p['machines']: m['currently_' + constraint] = True
    if constraint == 'predecessor': p['operations'][0]['predecessor_ids'] = ['previous']
    assert checked(p, plan).metrics()['avoidable_idle'] == 0


def test_batch_key_bounds_and_no_double_count():
    p, plan = fixture()
    p['operations'] = [op('a'), op('b'), op('c')]
    for o in p['operations']: o.update(batch_min=2, batch_max=2)
    assert checked(p, plan).metrics()['avoidable_idle'] == 1
    p['operations'][1]['batch_key'] = ['different']
    p['operations'][2]['batch_max'] = 3
    assert checked(p, plan).metrics()['avoidable_idle'] == 0


@pytest.mark.parametrize('conditional,dispatched,pending,expected', [
    (False, False, False, 1), (False, False, True, 1),
    (True, False, False, 0), (True, True, False, 1), (True, True, True, 0)])
def test_holds(conditional, dispatched, pending, expected):
    p, plan = fixture(); plan['holds'] = [{'machine': 1, 'until': 20}]
    if conditional: plan['holds'][0]['after_task_id'] = 'anchor'
    if pending: plan['tasks'] = [task(mid=1)]
    r = {'tasks': [{'task_id': 'anchor', 'state': 'done'}]} if dispatched else {}
    l = checked(p, plan, r)
    assert l.metrics()['explicit_wait_idle'] == expected
    assert l.metrics()['avoidable_idle'] == (0 if pending else 1)
    ledger_apply(l, {'time': 20})
    assert l.metrics()['explicit_wait_idle'] == 0


def test_queue_does_not_hide_unreserved_work_and_invalid_receipts():
    p, plan = fixture(); p['operations'].append(op('w1703:86:1'))
    plan['tasks'] = [task(mid=1, not_before=50)]
    assert checked(p, plan).metrics()['avoidable_idle'] == 1
    for state in ('invalid', 'running', 'done'):
        r = {'tasks': [{'task_id': 't', 'state': state}]}
        l = checked(p, plan, r)
        assert l.rows()['a']['state'] == state
        assert l.metrics()['avoidable_idle'] == 1
    p['operations'] = []
    assert checked(p, plan, {'tasks': [{'task_id': 't', 'state': 'running'}]}).rows()['a']['state'] == 'running'


@pytest.mark.parametrize('seed', [17, 42, 109])
def test_incremental_matches_rebuild(seed):
    rng = random.Random(seed); p, plan = fixture(); l = ledger_from_scratch(p, plan)
    reference = {'operations': {'a': op()}, 'machines': {m['machine']: deepcopy(m) for m in p['machines']},
                 'tasks': {}, 'holds': {}, 'receipts': {}, 'task_receipts': {}}
    for i in range(250):
        name = rng.choice(['operations', 'machines', 'tasks', 'holds', 'receipts', 'task_receipts'])
        oid = rng.choice(['a', 'b', 'c'])
        if name == 'operations': row = op(oid); row['conditional'] = rng.choice([True, False]); key = oid
        elif name == 'machines': row = dict(p['machines'][rng.randrange(2)], currently_busy=rng.choice([True, False])); key = row['machine']
        elif name == 'tasks': row = task(oid); row['id'] = 't' + oid; key = row['id']
        elif name == 'holds': row = {'id': 'h', 'machine': 1, 'until': i + 5}; key = 'h'
        elif name == 'receipts': row = {'operation_id': oid, 'state': rng.choice(['done', 'running', 'invalid'])}; key = oid
        else: row = {'task_id': 't' + oid, 'state': rng.choice(['done', 'running', 'invalid'])}; key = row['task_id']
        delta = {'time': i, name: {'upsert': [row]} if rng.random() < .8 else {'delete': [key]}}
        ledger_apply(l, delta)
        assert l.update_work <= 4
        if 'upsert' in delta[name]: reference[name][key] = deepcopy(row)
        else: reference[name].pop(key, None)
        p2 = {'time': i, 'operations': list(reference['operations'].values()), 'machines': list(reference['machines'].values())}
        plan2 = {'created_at': 0, 'tasks': list(reference['tasks'].values()), 'holds': list(reference['holds'].values())}
        r = {'operations': list(reference['receipts'].values()), 'tasks': list(reference['task_receipts'].values())}
        rebuilt = ledger_from_scratch(p2, plan2, r)
        assert l.rows() == rebuilt.rows()
        assert l.metrics() == rebuilt.metrics()
        assert reconcile(l.metrics(), p2, plan2, r)['ok']
        before = deepcopy(l.rows()); ledger_apply(l, delta); assert l.rows() == before


def test_update_cost_independent_of_wip():
    p, plan = fixture(); p['operations'] = [op(str(i)) for i in range(10000)]
    l = ledger_from_scratch(p, plan)
    ledger_apply(l, {'time': 100}); assert l.update_work == 0
    ledger_apply(l, {'operations': {'upsert': [op('0')]}}); assert l.update_work == 1


def test_audit_detects_mismatch():
    p, plan = fixture(); metrics = checked(p, plan).metrics(); metrics['avoidable_idle'] = 99
    assert not reconcile(metrics, p, plan)['ok']
