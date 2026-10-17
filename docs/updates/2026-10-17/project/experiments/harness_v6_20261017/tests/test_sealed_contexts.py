import json
import os
import sqlite3
import pytest
from harness_v6.sealed_contexts import classify_sealed_contexts, SQLiteContextReader
from test_ledger import fixture, task, op


class Reader:
    def __init__(self, rows): self.rows = rows
    def contexts(self): return iter(self.rows)


def context():
    p, plan = fixture(); p['time'] = 1000; plan['tasks'] = [task(not_before=1100)]
    return {'time': 1000, 'context_ref': 'c', 'problem': p, 'base_plan': plan,
            'trigger': {'reason': 'uncovered_demand', 'machines': [{'machine': 1, 'candidate_count': 1}]}}


def test_old_counts_new_exceptions_and_opportunity_seconds():
    rows = [{'group': g, 'context': context()} for g, n in [('G0', 10), ('G1', 15), ('G2', 4)] for _ in range(n)]
    r = classify_sealed_contexts(Reader(rows))
    assert r['old_counts_match'] and not r['new_rule_exceptions']
    assert r['reserved_but_earlier_startable_count'] == 29
    assert r['potential_idle_seconds'] == 2900
    c = context(); c['problem']['operations'].append(op('w1703:86:1', eligible_machines=[2]))
    r = classify_sealed_contexts(Reader([{'group': 'G0', 'context': c}]))
    assert len(r['new_rule_exceptions']) == 1
    assert len(r['w1703_witnesses']) == 1


def test_sqlite_adapter_synthetic_read_only(tmp_path):
    path = tmp_path / 'fixture.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE contexts (group_name TEXT, payload TEXT)')
        db.execute('INSERT INTO contexts VALUES (?, ?)', ('G0', json.dumps(context())))
    r = SQLiteContextReader(path, 'SELECT group_name, payload FROM contexts')
    assert classify_sealed_contexts(r)['old_rule_counts'] == {'G0': 1}
    with pytest.raises(sqlite3.OperationalError):
        list(SQLiteContextReader(path, 'DELETE FROM contexts RETURNING group_name, payload').contexts())


def test_mac_sealed_classification():
    path = os.environ.get('V6_SEALED_DB'); query = os.environ.get('V6_SEALED_SELECT')
    if not path or not query:
        pytest.skip('Mac-only sealed evidence absent; set V6_SEALED_DB and V6_SEALED_SELECT')
    report = classify_sealed_contexts(SQLiteContextReader(path, query))
    output = os.environ.get('V6_CLASSIFICATION_REPORT')
    if output:
        from pathlib import Path
        Path(output).write_text(json.dumps(report, sort_keys=True, separators=(',', ':')))
    assert report['old_counts_match']
    assert report['new_rule_exceptions'] == [], report['new_rule_exceptions']
    assert report['w1703_witnesses']


def test_mac_snapshot_26_pending():
    path = os.environ.get('V6_SEALED_DB'); query = os.environ.get('V6_SEALED_SELECT')
    if not path or not query:
        pytest.skip('Mac-only G0 1649.82 sealed context absent')
    from harness_v6.ledger import ledger_from_scratch
    from harness_v6.snapshot import build_snapshot, stable_prefix, tiktoken_counter
    pytest.importorskip('tiktoken', reason='Mac-only pinned tokenizer dependency is absent')
    found = False
    for entry in SQLiteContextReader(path, query).contexts():
        ctx = entry['context']
        if entry['group'] != 'G0' or abs(ctx['time'] - 1649.82) > .01: continue
        dispatched = set(ctx['execution_state']['dispatched_task_ids'])
        receipts = {'tasks': [{'task_id': t, 'state': 'running'} for t in dispatched]}
        ledger = ledger_from_scratch(ctx['problem'], ctx['base_plan'], receipts)
        pending = [t for t in ctx['base_plan']['tasks'] if t['id'] not in dispatched]
        assert len(pending) == 26
        payload = build_snapshot(stable_prefix(tool_descriptions={}, routing=[], machine_groups=[]), ledger,
            state_version=ctx['state_revision'], running_jobs=ctx.get('running_jobs', []),
            last_cycle_receipt=None, model_notes='', token_budget=10**9, token_counter=tiktoken_counter())
        current = json.loads(payload.split(b'\n', 1)[1])
        assert current['pending_tasks'] == pending
        assert current['holds'] == ctx['base_plan']['holds']
        assert len(current['unreserved_ready']) == sum(r['ready'] and r['state'] == 'ready_unreserved' for r in ledger.rows().values())
        found = True
    assert found, 'G0 1649.82 context must be included in the SELECT'
