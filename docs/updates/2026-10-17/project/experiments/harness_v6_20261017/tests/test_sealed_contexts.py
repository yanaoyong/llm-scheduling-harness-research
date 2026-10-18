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
    r = classify_sealed_contexts(Reader(rows), expected={'G0':10,'G1':15,'G2':4}, witness_operation='w1703:86:1')
    assert r['old_counts_match'] and not r['new_rule_exceptions']
    assert r['reserved_but_earlier_startable_count'] == 29
    assert r['potential_idle_seconds'] == 2900
    c = context(); c['problem']['operations'].append(op('w1703:86:1', eligible_machines=[2]))
    r = classify_sealed_contexts(Reader([{'group': 'G0', 'context': c}]), expected={'G0':10,'G1':15,'G2':4}, witness_operation='w1703:86:1')
    assert len(r['new_rule_exceptions']) == 1
    assert len(r['operation_witnesses']) == 1


def test_sqlite_adapter_synthetic_read_only(tmp_path):
    path = tmp_path / 'fixture.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE contexts (group_name TEXT, payload TEXT)')
        db.execute('INSERT INTO contexts VALUES (?, ?)', ('G0', json.dumps(context())))
    r = SQLiteContextReader(path, 'SELECT group_name, payload FROM contexts')
    assert classify_sealed_contexts(r, expected={'G0':1}, witness_operation='w1703:86:1')['old_rule_counts'] == {'G0': 1}
    with pytest.raises(sqlite3.OperationalError):
        list(SQLiteContextReader(path, 'DELETE FROM contexts RETURNING group_name, payload').contexts())


def test_mac_sealed_classification():
    path = os.environ.get('V6_SEALED_DB'); query = os.environ.get('V6_SEALED_SELECT')
    if not path or not query:
        pytest.skip('Mac-only sealed evidence absent; set V6_SEALED_DB and V6_SEALED_SELECT')
    report = classify_sealed_contexts(SQLiteContextReader(path, query), expected={'G0':10,'G1':15,'G2':4}, witness_operation='w1703:86:1')
    output = os.environ.get('V6_CLASSIFICATION_REPORT')
    if output:
        from pathlib import Path
        Path(output).write_text(json.dumps(report, sort_keys=True, separators=(',', ':')))
    assert report['old_counts_match']
    # Phase H: M1(b) permits individually justified exceptions (DECISIONS_v6).
    expected = {('G0', 'context:97eada3675ec457ca5a28750'),
                ('G1', 'context:61d6652b89614a3aa60bfe1e')}
    exceptions = report['new_rule_exceptions']
    assert len(exceptions) == len(expected)
    assert {(r['group'], r['context_ref']) for r in exceptions} == expected
    from harness_v6.audit_ledger import audit_ledger, reconcile
    from harness_v6.ledger import ledger_from_scratch
    checked = set()
    for entry in SQLiteContextReader(path, query).contexts():
        ctx = entry['context']; key = (entry['group'], ctx['context_ref'])
        if key not in expected:
            continue
        record = next(r for r in exceptions if (r['group'], r['context_ref']) == key)
        receipts = {'tasks': [{'task_id': tid, 'state': 'running'}
                             for tid in ctx['execution_state']['dispatched_task_ids']]}
        ledger = ledger_from_scratch(ctx['problem'], ctx['base_plan'], receipts)
        metrics = ledger.metrics()
        independent = audit_ledger(ctx['problem'], ctx['base_plan'], receipts)
        assert reconcile(metrics, ctx['problem'], ctx['base_plan'], receipts)['ok']
        assert independent['avoidable_idle'] == metrics['avoidable_idle'] == 1
        assert record['metrics'] == metrics
        assert ctx['time'] == pytest.approx(1593.1323091758827, abs=1e-6)
        assert independent['avoidable_idle_matches'] == [
            {'machine': 325, 'operation_ids': ['w1703:86:1']}]
        old_gap_ops = {o['operation_id'] for o in ctx['problem']['operations']
                       if not o.get('conditional', False) and o['release_time'] <= ctx['time']
                       and any(g['machine'] in o['eligible_machines']
                               for g in ctx['trigger']['machines'])}
        reserved = {oid for t in ledger.pending_tasks() for oid in t['operation_ids']}
        assert old_gap_ops and old_gap_ops <= reserved
        witnesses = {oid for m in independent['avoidable_idle_matches'] for oid in m['operation_ids']}
        assert witnesses.isdisjoint(reserved | old_gap_ops)
        assert all(ledger.rows()[oid]['state'] == 'ready_unreserved' for oid in witnesses)
        opportunities = {o['operation_id'] for o in metrics['reserved_but_earlier_startable']}
        assert witnesses.isdisjoint(opportunities)
        # Remove only the unreserved witness: reserved opportunities remain,
        # but cannot cause a trigger in either implementation.
        problem = dict(ctx['problem'], operations=[o for o in ctx['problem']['operations']
                                                  if o['operation_id'] not in witnesses])
        without = ledger_from_scratch(problem, ctx['base_plan'], receipts).metrics()
        assert without['reserved_but_earlier_startable'] == metrics['reserved_but_earlier_startable']
        assert without['avoidable_idle'] == 0
        assert audit_ledger(problem, ctx['base_plan'], receipts)['avoidable_idle'] == 0
        checked.add(key)
    assert checked == expected
    assert report['operation_witnesses']


def test_mac_snapshot_26_pending():
    path = os.environ.get('V6_SEALED_DB'); query = os.environ.get('V6_SEALED_SELECT')
    if not path or not query:
        pytest.skip('Mac-only G0 1649.82 sealed context absent')
    from harness_v6.ledger import ledger_from_scratch
    from harness_v6.snapshot import build_snapshot, stable_prefix, tiktoken_counter
    pytest.importorskip('tiktoken', reason='Mac-only pinned tokenizer dependency is absent')
    from mac_fixture import bundle
    evidence = bundle('g0_snapshot')['g0_snapshot']
    found = False
    for entry in SQLiteContextReader(path, query).contexts():
        ctx = entry['context']
        if entry['group'] != 'G0' or abs(ctx['time'] - 1649.82) > .01: continue
        dispatched = set(ctx['execution_state']['dispatched_task_ids'])
        receipts = {'tasks': [{'task_id': t, 'state': 'running'} for t in dispatched]}
        ledger = ledger_from_scratch(ctx['problem'], ctx['base_plan'], receipts)
        pending = [t for t in ctx['base_plan']['tasks'] if t['id'] not in dispatched]
        assert len(ctx['base_plan']['tasks']) == 26
        assert len(pending) == 23
        assert dispatched == {'d32-l', 'd36-e', 'd39-g'}
        assert evidence['context_ref'] == ctx['context_ref']
        assert evidence['time'] == ctx['time']
        payload = build_snapshot(stable_prefix(tool_descriptions={}, routing=[], machine_groups=[]), ledger,
            state_version=ctx['state_revision'], running_jobs=evidence['running_jobs'],
            last_cycle_receipt=None, model_notes='', token_budget=10**9, token_counter=tiktoken_counter())
        current = json.loads(payload.split(b'\n', 1)[1])
        assert current['pending_tasks'] == pending
        assert current['running_jobs'] == evidence['running_jobs']
        visible = {}
        trace = bundle('g0_trace')['g0_trace']
        for task_row in ctx['base_plan']['tasks']:
            if task_row['id'] not in dispatched:
                continue
            events = [e for e in trace if e['kind'] == 'dispatch'
                      and e.get('plan_task_id') == task_row['id']
                      and e.get('plan_version') == ctx['base_plan']['version']]
            assert len(events) == 1
            assert events[0]['lots'] == task_row['lot_ids']
            assert events[0]['steps'] == task_row['steps']
            assert events[0]['visits'] == task_row['visits']
            jobs = [j for j in current['running_jobs']
                    if j['job'] == events[0]['job'] and j['machine'] == task_row['machine']
                    and set(task_row['lot_ids']) <= set(j['lot_ids'])
                    and j['started_at'] == events[0]['time']]
            assert len(jobs) == 1, task_row
            visible[task_row['id']] = jobs[0]['job']
        assert visible == {'d32-l': 976, 'd36-e': 974, 'd39-g': 975}
        assert {t['id'] for t in current['pending_tasks']} | set(visible) == {
            t['id'] for t in ctx['base_plan']['tasks']}
        assert current['holds'] == ctx['base_plan']['holds']
        assert len(current['unreserved_ready']) == sum(r['ready'] and r['state'] == 'ready_unreserved' for r in ledger.rows().values())
        found = True
    assert found, 'G0 1649.82 context must be included in the SELECT'
