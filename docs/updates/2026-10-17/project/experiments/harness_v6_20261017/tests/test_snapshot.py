import json
import pytest
from harness_v6.ledger import ledger_from_scratch, ledger_apply
from harness_v6.snapshot import (stable_prefix, build_snapshot, HistorySummary,
                                 SnapshotBudgetExceeded, tiktoken_counter)
from test_ledger import fixture, op, task


def prefix():
    return stable_prefix(tool_descriptions={'read_entities': 'exact public facts'}, routing=[{'route': 'P'}], machine_groups=[{'family': 'F'}])


def snapshot(l, **kw):
    args = dict(state_version='v', running_jobs=[], last_cycle_receipt=None, model_notes='', token_budget=100000)
    args.update(kw)
    return build_snapshot(prefix(), l, **args)


def test_complete_deterministic_snapshot():
    p, plan = fixture(); p['operations'] = [op(str(i)) for i in range(50)]
    plan['tasks'] = [dict(task(str(i)), id=f't{i}') for i in range(26)]
    plan['holds'] = [{'machine': 2, 'until': 50}, {'machine': 1, 'until': 0}]
    l = ledger_from_scratch(p, plan)
    payload = snapshot(l); current = json.loads(payload.split(b'\n', 1)[1])
    assert current['pending_tasks'] == plan['tasks']
    assert current['holds'] == plan['holds']
    assert {r['operation_id'] for r in current['unreserved_ready']} == {str(i) for i in range(26, 50)}
    assert snapshot(l) == payload
    ledger_apply(l, {'time': 11})
    assert snapshot(l).split(b'\n')[0] == payload.split(b'\n')[0]


def test_running_invalid_notes_and_receipt():
    p, plan = fixture(); plan['tasks'] = [task()]
    l = ledger_from_scratch(p, plan, {'tasks': [{'task_id': 't', 'state': 'invalid'}]})
    data = json.loads(snapshot(l, running_jobs=[{'job': 'j'}], model_notes='remember', last_cycle_receipt={'ok': True}).split(b'\n')[1])
    assert data['invalid_tasks'] == plan['tasks']
    assert data['running_jobs'] == [{'job': 'j'}]
    assert data['last_cycle_receipt'] == {'ok': True}
    assert data['model_notes'] == 'remember'


def test_fail_closed_pluggable_counter_and_full_only():
    p, plan = fixture(); l = ledger_from_scratch(p, plan)
    with pytest.raises(SnapshotBudgetExceeded) as e:
        snapshot(l, token_budget=10, token_counter=lambda _: 11)
    assert e.value.report['tokens'] == 11 and e.value.report['dropped_rows'] == 0
    assert snapshot(l, token_budget=11, token_counter=lambda _: 11)
    for mode in ('partitioned', 'tiered'):
        with pytest.raises(TypeError): snapshot(l, mode=mode)


def test_long_sequence_has_constant_history_and_bounded_size():
    p, plan = fixture(); l = ledger_from_scratch(p, plan); history = HistorySummary(); sizes = []
    for cycle in range(1000, 2500):
        history = history.append({'cycle': cycle, 'arbitrarily_large_event': 'x' * 1000})
        ledger_apply(l, {'time': cycle})
        sizes.append(len(snapshot(l, state_version=f'v{cycle}', history=history)))
        assert len(history.digest) == 64
    assert len(set(sizes)) == 1


def test_mac_tokenizer():
    pytest.importorskip('tiktoken', reason='Mac-only pinned tokenizer dependency is absent')
    counter = tiktoken_counter()
    assert counter('hello world') == 2


def test_default_encoding_is_v5_comparable(monkeypatch):
    import sys
    from types import SimpleNamespace
    names=[]
    monkeypatch.setitem(sys.modules,'tiktoken',SimpleNamespace(get_encoding=lambda name:
        (names.append(name) or SimpleNamespace(encode=lambda text,**kw:[1]))))
    assert tiktoken_counter()('text')==1
    assert names==['o200k_base']
