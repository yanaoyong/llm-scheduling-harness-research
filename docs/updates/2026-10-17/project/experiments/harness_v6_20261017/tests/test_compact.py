"""Representation properties, wire limits and full-request fail-closed behavior."""
from copy import deepcopy
import json
import math
import random
import pytest
from harness_v6.compact import encode_prefix, encode_current, decode_snapshot, normalize
from harness_v6.snapshot import build_snapshot, stable_prefix
from harness_v6.ledger import ledger_from_scratch
from test_ledger import fixture, op, task


def equivalent(expected, actual):
    assert type(actual) is type(expected), (expected, actual)
    if isinstance(expected, dict):
        assert expected.keys() == actual.keys()
        for key in expected:
            equivalent(expected[key], actual[key])
    elif isinstance(expected, list):
        assert len(expected) == len(actual)
        for a, b in zip(expected, actual):
            equivalent(a, b)
    elif isinstance(expected, float):
        assert math.isclose(expected, actual, rel_tol=1e-9, abs_tol=0)
        if expected == 0:
            assert math.copysign(1, expected) == math.copysign(1, actual)
    else:
        assert expected == actual


@pytest.mark.parametrize('snapshot_format', ['explicit', 'dense'])
@pytest.mark.parametrize('seed', range(30))
def test_generated_routes_machines_ledger_roundtrip(seed, monkeypatch, snapshot_format):
    rng = random.Random(seed)
    p, plan = fixture()
    ids = [1, 2, 8, 10, 11]
    rng.shuffle(ids)
    machines = [dict(id=i, family='F' if i < 8 else 'G', group='g', load=0,
                     unload=1.0, cascading=False) for i in ids]
    p['machines'] = [dict(machine=i, family='F' if i < 8 else 'G', cascading=False,
                         available_at=10, currently_busy=False, currently_down=False,
                         availability_basis='same\tconstant\n说明\u2028', min_left=0, min_setup='') for i in ids]
    p['operations'] = [op(str(i), eligible_machines=rng.choice([[1, 2], [1, 8], [2, 1], [], [8, 10, 11]])) for i in range(40)]
    for o in p['operations']:
        o.update(release_time=rng.choice([0, 0.0, 3.5999999999999996]), setup=rng.choice([None, '', 'A']),
                 qualification_uncertain=rng.choice([False, True]))
    plan['tasks'] = [dict(task(str(i)), id=f't{i}', not_before=rng.choice([0, 0.0])) for i in range(5)]
    plan['holds'] = [dict(machine=8, until=20, after_task_id='t0'), dict(machine=10, until=0)]
    ledger = ledger_from_scratch(p, plan, {'tasks':[{'task_id':'t3','state':'invalid'}]})
    route = [dict(step=i, family='F', processing=dict(type='uniform',m=1.0,offset=3.5999999999999996),
                  transport=dict(type='constant', c=0 if i % 2 else 0.0), setup=None if i % 2 else '',
                  extra=[False, None, '', -0.0, 1e-20, 'CURRENT\n', '\t']) for i in range(1, 8)]
    if seed % 2:
        route[0]['step'] = 1.0  # Noncanonical inputs retain step type verbatim.
    prefix_obj = dict(rules='rule', tools=[], routing={'r':route, 'empty':[], 'r2':deepcopy(route)}, machine_groups=sorted(machines, key=lambda m: m['id']))
    prefix = encode_prefix(prefix_obj, snapshot_format=snapshot_format)
    jobs = [dict(job=i, started_at=rng.random(), machine=1, lot_ids=[str(i)]) for i in range(10)]
    captured = []
    import harness_v6.snapshot as snap
    original = snap.encode_current
    def capture(prefix_obj, current, **kwargs):
        captured.append(deepcopy(current))
        return original(prefix_obj, current, **kwargs)
    monkeypatch.setattr(snap, 'encode_current', capture)
    args = dict(snapshot_format=snapshot_format, state_version=seed, running_jobs=jobs, last_cycle_receipt={'accepted':False,'violations':[{'code':'x'}]},
                model_notes='\u2028\n\t! null ""', token_budget=100000)
    payload = build_snapshot(prefix, ledger, **args)
    decoded_prefix, current = decode_snapshot(payload)
    equivalent(prefix_obj, decoded_prefix)
    equivalent(captured[0], current)
    assert build_snapshot(prefix, ledger, **args) == payload
    assert payload.startswith(prefix)
    assert b'$positions' not in payload
    assert [r['operation_id'] for r in current['unreserved_ready']] == sorted(r['operation_id'] for r in current['unreserved_ready'])
    assert [m['machine'] for m in current['machines']] == sorted(ids)
    assert stable_prefix(tool_descriptions=[], routing={}, machine_groups=machines, snapshot_format=snapshot_format) == stable_prefix(tool_descriptions=[], routing={}, machine_groups=list(reversed(machines)), snapshot_format=snapshot_format)
    from harness_v6.compact import sections, CURRENT
    groups = sections(payload.split(CURRENT, 1)[1].decode())['ready_groups']
    for group in groups:
        oid = group['$operations'][0]
        eligible = ledger.operations[oid]['eligible_machines']
        assert len(group['$eligible']) == 2
        if eligible in ([1, 2], [8, 10, 11]):
            assert group['$eligible'][0] == 'family'
        else:
            assert group['$eligible'][0] == 'set'
    assert {m['machine'] for m in current['machines']} == set(ledger.machines)
    assert {j['job'] for j in current['running_jobs']} == {j['job'] for j in jobs}
    assert {t['id'] for t in current['pending_tasks']} == {t['id'] for t in ledger.pending_tasks()}
    assert {o['operation_id'] for o in current['unreserved_ready']} == {
        oid for oid, r in ledger.rows().items() if r['ready'] and r['state']=='ready_unreserved'}



def test_canonical_rows_ignore_insertion_order_and_keep_explicit_eligible_order():
    from harness_v6.snapshot import current_state
    p, plan = fixture()
    p['operations'] = [op(oid, eligible_machines=eligible) for oid, eligible in
                       [('z', [2, 1]), ('a', [1, 2]), ('m', [1])]]
    p['machines'].reverse()
    ledger = ledger_from_scratch(p, plan)
    args = dict(state_version=0, running_jobs=[], last_cycle_receipt=None, model_notes='')
    current = current_state(ledger, **args)
    assert [r['operation_id'] for r in current['unreserved_ready']] == ['a', 'm', 'z']
    assert [m['machine'] for m in current['machines']] == [1, 2]
    prefix = dict(rules='', tools=[], routing={}, machine_groups=[dict(id=2, family='F'), dict(id=1, family='F')])
    original = deepcopy((prefix, current))
    wire = encode_prefix(prefix) + encode_current(prefix, current)
    decoded_prefix, decoded_current = decode_snapshot(wire)
    assert [m['id'] for m in decoded_prefix['machine_groups']] == [1, 2]
    equivalent(current, decoded_current)
    assert (prefix, current) == original
    from harness_v6.compact import sections, CURRENT
    encoded = sections(wire.split(CURRENT, 1)[1].decode())
    refs = {oid: g['$eligible'] for g in encoded['ready_groups'] for oid in g['$operations']}
    assert refs['a'] == ['family', 'F']
    sets = {r['id']: r['machines'] for r in encoded['eligible_sets']}
    assert refs['z'][0] == refs['m'][0] == 'set'
    assert sets[refs['z'][1]] == [2, 1]
    assert sets[refs['m'][1]] == [1]
    assert b'$positions' not in wire


def test_absence_and_null_in_heterogeneous_tables():
    prefix = dict(rules='', tools=[], routing={}, machine_groups=[])
    current = dict(machines=[], unreserved_ready=[], holds=[{}, {'until':None}, {'until':''}],
                   last_cycle_receipt={'x':None}, running_jobs=[])
    equivalent((prefix), decode_snapshot(encode_prefix(prefix)+encode_current(prefix,current))[0])
    equivalent(current, decode_snapshot(encode_prefix(prefix)+encode_current(prefix,current))[1])


@pytest.mark.parametrize('count', [0, 50, 51, 137])
def test_receipt_bounds_all_errors_and_idempotence(count):
    from test_cycle_submit import submitter
    all_errors = [{'code': 'a' if i % 2 else 'b', 'detail':str(i)} for i in range(count)]
    s = submitter(physical_precheck=lambda *args: deepcopy(all_errors))
    s.base_plan['valid_until'] = 900
    result = s.submit_plan(1, 'bounded', {})
    assert result['accepted'] == (count == 0)
    assert result['violations'] == all_errors[:50]
    assert result['violation_count'] == count
    assert sum(result['counts_by_code'].values()) == count
    assert result['truncated'] == (count > 50)
    assert s.submit_plan(1, 'bounded', {}) == result
    assert len(all_errors) == count


def test_validate_and_submit_bounded_and_removed_tool(tmp_path):
    from test_mcp_session import setup_cycle
    from harness_v6.mcp_server import TOOLS
    server, _ = setup_cycle(tmp_path)
    try:
        server.submitter.base_plan['valid_until'] = 900
        server.submitter.physical_precheck = lambda *args: [{'code':'test'} for _ in range(51)]
        for tool in ('validate_plan', 'submit_plan'):
            result = server.call(tool, dict(expected_state_version=0, submission_id='v', delta={}))
            assert result['violation_count'] == 51
            assert len(result['violations']) == 50 and result['truncated']
            assert not result['accepted']
        assert set(TOOLS) == {'read_entities','validate_plan','submit_plan'}
        assert server.call('get_' + 'decision_snapshot', {})['isError']
    finally:
        server.close()


def test_ids_query_rejects_oversize_without_partial_read():
    from harness_v6.facts import FactReader, build_facts
    from harness_v6.contracts import HarnessError
    p = dict(machines=[], operations=[dict(operation_id=str(i)) for i in range(513)])
    reader = FactReader('x', build_facts(p, dict(tasks=[],holds=[])))
    with pytest.raises(HarnessError, match='entity_ids_limit'):
        reader.read(dict(kind='operations', ids=[str(i) for i in range(513)]))
    assert reader.cache == {}
    assert len(reader.read(dict(kind='operations', ids=[str(i) for i in range(512)]))['entities']) == 512


@pytest.mark.parametrize('extra,stop', [(0,False),(1,True)])
def test_whole_request_budget_boundary(tmp_path, extra, stop):
    from harness_v6.synthetic import SyntheticRun
    run = SyntheticRun(directory=tmp_path)
    run.token_counter = lambda _: 100
    run.context_token_budget = 200
    run.request_overhead_tokens = 60
    run.output_reserve_tokens = 40 + extra
    run.step()
    assert (run.cycle.stop_reason == 'context_budget_exceeded') == stop
    if stop:
        report = json.loads((tmp_path/'budget_report.json').read_text())
        assert report['snapshot_tokens'] == 100
        assert report['request_overhead_tokens'] == 60
        assert report['output_reserve_tokens'] == 41
        assert report['context_token_budget'] == 200
        assert report['request_tokens'] == 201
        assert not list(tmp_path.glob('cycle-*'))
        assert run.store.latest()['extra']['budget_report'] == report
