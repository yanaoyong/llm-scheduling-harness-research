"""Offline measurements from the public sealed fixture; never runs a planner."""
from harness_v6.compact import normalize
from harness_v6.snapshot import decode_snapshot
import argparse
import json
from pathlib import Path
from harness_v6.contracts import digest, encode
from harness_v6.factory_v6 import capture, restore
from harness_v6.ledger import ledger_from_scratch
from harness_v6.replay import equivalence
from harness_v6.sealed_contexts import SQLiteContextReader, classify_sealed_contexts
from harness_v6.snapshot import build_snapshot, stable_prefix, tiktoken_counter, SnapshotBudgetExceeded


def validate(directory):
    if not directory.resolve().is_relative_to(Path('/workspace/v6-mac-env/work')):
        raise ValueError('outputs must be under /workspace/v6-mac-env/work')
    bundle = json.loads((directory/'fixture.json').read_bytes())
    reader = SQLiteContextReader(directory/'contexts.sqlite', 'SELECT group_name,payload FROM contexts')
    report = classify_sealed_contexts(reader, expected={'G0':10,'G1':15,'G2':4}, witness_operation='w1703:86:1')
    (directory/'classification.json').write_bytes(encode(report))
    print('classification', report['old_rule_counts'], len(report['new_rule_exceptions']), flush=True)
    seed = bundle['mixed_702']
    env = restore(seed['state'], seed['trace'], data_dir=bundle['data_dir'])
    state = capture(env)
    result = {'roundtrip_sha256': digest(state), 'roundtrip_equal': capture(restore(state, env.trace, data_dir=bundle['data_dir'])) == state}
    replay = equivalence(env, bundle['g0_committed_plans'], bundle['g0_trace'])
    (directory/'replay.json').write_bytes(encode(replay))
    result['replay'] = {k: v for k, v in replay.items() if k != 'errors'}
    print('replay', result['replay'], str(replay.get('errors'))[:500], flush=True)
    counter = tiktoken_counter()
    from harness_v6.mcp_server import TOOLS
    prefix = stable_prefix(tool_descriptions=[{'name':name,'description':name,'inputSchema':schema} for name,schema in TOOLS.items()],
                           routing=env.manifest['routes'], machine_groups=env.manifest['machines'])
    case_refs = {c['context_ref'] for c in bundle['w1462_case']['calls']}
    exception_refs = {c['context_ref'] for c in report['new_rule_exceptions']}
    result['exception_details'] = []
    result['endpoint_metrics'] = {}
    for entry in reader.contexts():
        ctx = entry['context']
        if ctx.get('measurement'):
            result['endpoint_metrics'][entry['group']] = ledger_from_scratch(ctx['problem'],ctx['base_plan'],ctx['ledger_receipts']).metrics()
            continue
        if ctx['context_ref'] not in case_refs | exception_refs and not (entry['group']=='G0' and abs(ctx['time']-1649.82)<.01):
            continue
        execution = ctx['execution_state']
        receipts = {'tasks': [{'task_id': tid, 'state': 'running'} for tid in execution['dispatched_task_ids']]}
        ledger = ledger_from_scratch(ctx['problem'],ctx['base_plan'],receipts)
        if ctx['context_ref'] in exception_refs:
            from harness_v6.audit_ledger import reconcile
            metrics = ledger.metrics()
            audit = reconcile(metrics,ctx['problem'],ctx['base_plan'],receipts)
            result['exception_details'].append(dict(group=entry['group'], context_ref=ctx['context_ref'], time=ctx['time'],
                old_trigger=ctx['trigger'], metrics=metrics, independent_audit=audit,
                queued_on_witness_machine=[t['id'] for t in ledger.pending_tasks() if t['machine']==325]))
        if ctx['context_ref'] in case_refs:
            result['w1462'] = {'context_ref': ctx['context_ref'], 'metrics': ledger.metrics()}
        if entry['group'] != 'G0' or abs(ctx['time']-1649.82) > .01:
            continue
        from build_sealed_fixture import Archive
        provenance = json.loads((directory/'provenance.json').read_bytes())
        source = next(Path(p).parent for p in provenance if p.endswith('/G0/events.sqlite3.public.sql'))
        archive = Archive(source,directory,provenance)
        head = json.loads(archive.db.execute("SELECT value FROM metadata WHERE key='head'").fetchone()[0])
        state = archive.obj(head['state_ref'])
        assert state['t'] == ctx['time']
        running = [dict(job=int(i),machine=j['machine'],lot_ids=j['lots'],started_at=j['start']) for i,j in sorted(state['jobs'].items(),key=lambda item:int(item[0])) if not j['done']]
        (directory/'provenance.json').write_bytes(encode(provenance))
        args = dict(state_version=ctx['state_revision'], running_jobs=running,
                    last_cycle_receipt=None, model_notes='', token_counter=counter)
        payload = build_snapshot(prefix, ledger, token_budget=10**9, **args)
        current = decode_snapshot(payload)[1]
        pending = [t for t in ctx['base_plan']['tasks'] if t['id'] not in execution['dispatched_task_ids']]
        assert current['pending_tasks'] == normalize(pending)
        # Phase H: account for all base tasks across pending and actual running jobs.
        assert len(ctx['base_plan']['tasks']) == 26 and len(pending) == 23
        assert running == bundle['g0_snapshot']['running_jobs']
        visible = {}
        for task in ctx['base_plan']['tasks']:
            if task['id'] not in execution['dispatched_task_ids']:
                continue
            events = [e for e in bundle['g0_trace'] if e['kind'] == 'dispatch'
                      and e.get('plan_task_id') == task['id']
                      and e.get('plan_version') == ctx['base_plan']['version']]
            assert len(events) == 1
            assert events[0]['lots'] == task['lot_ids']
            assert events[0]['steps'] == task['steps']
            assert events[0]['visits'] == task['visits']
            jobs = [j for j in current['running_jobs'] if j['job'] == events[0]['job'] and j['machine'] == task['machine']
                    and set(task['lot_ids']) <= set(j['lot_ids']) and j['started_at'] == normalize(events[0]['time'])]
            assert len(jobs) == 1
            visible[task['id']] = jobs[0]['job']
        assert visible == {'d32-l': 976, 'd36-e': 974, 'd39-g': 975}
        assert current['holds'] == normalize(ctx['base_plan']['holds'])
        expected_ready = {oid for oid,row in ledger.rows().items() if row['ready'] and row['state']=='ready_unreserved'}
        assert {row['operation_id'] for row in current['unreserved_ready']} == expected_ready
        budget = bundle['sealed_input_budget']
        try:
            build_snapshot(prefix, ledger, token_budget=budget, **args)
        except SnapshotBudgetExceeded as error:
            result['snapshot'] = error.report
        else:
            result['snapshot'] = {'tokens':counter(payload.decode()), 'budget':budget, 'failed_closed':False}
        result['snapshot'].update(expected_pending=23, pending_count_matches=len(pending)==23, accounted_base_tasks=len(pending)+len(visible), dispatched_running_jobs=visible, actual_pending=len(pending), base_tasks=len(ctx['base_plan']['tasks']), dispatched_task_ids=execution['dispatched_task_ids'], holds=len(current['holds']), running_jobs=len(running), prefix_tokens=counter(prefix.decode()), context_ref=ctx['context_ref'])
    (directory/'validation.json').write_bytes(encode(result))
    print('snapshot',result.get('snapshot'),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('directory',type=Path)
    validate(parser.parse_args().directory)
