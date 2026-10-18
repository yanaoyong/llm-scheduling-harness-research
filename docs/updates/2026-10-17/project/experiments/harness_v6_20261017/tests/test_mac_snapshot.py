"""Complete public-state snapshot and real-token fail-closed check; no sealed alias."""
from harness_v6.delta_schema import model_task
from harness_v6.compact import normalize
from harness_v6.snapshot import decode_snapshot
import json
import pytest
from mac_fixture import environment
from harness_v6.ledger import ledger_read_view
from harness_v6.snapshot import stable_prefix,build_snapshot,tiktoken_counter,SnapshotBudgetExceeded


def test_public_complete_snapshot_and_budget():
    env,b=environment()
    observed=env.ledger_snapshot()
    ledger=ledger_read_view(observed['problem'],observed['plan'],observed['receipts'])
    prefix=stable_prefix(tool_descriptions=['read_entities','validate_plan','submit_plan'],
        routing=env.manifest['routes'],machine_groups=env.manifest['machines'])
    count=tiktoken_counter()
    args=dict(state_version=0,running_jobs=[dict(job=i,machine=j['machine'],lot_ids=j['lots'],started_at=j['start'])
        for i,j in sorted(env.jobs.items()) if not j['done']],last_cycle_receipt=None,model_notes='public mechanism',token_counter=count)
    payload=build_snapshot(prefix,ledger,token_budget=10**8,**args)
    current=decode_snapshot(payload)[1]
    assert current['pending_tasks']==normalize([model_task(t) for t in ledger.pending_tasks()])
    assert current['holds']==normalize(list(ledger.holds.values()))
    expected={oid for oid,r in ledger.rows().items() if r['ready'] and r['state']=='ready_unreserved'}
    assert {r['operation_id'] for r in current['unreserved_ready']}==expected
    tokens=count(payload.decode())
    with pytest.raises(SnapshotBudgetExceeded) as error:
        build_snapshot(prefix,ledger,token_budget=tokens-1,**args)
    assert error.value.report['tokens']==tokens and error.value.report['dropped_rows']==0


@pytest.mark.parametrize('snapshot_format', ['explicit', 'dense'])
def test_real_manifest_and_g0_compact_roundtrip(snapshot_format):
    import os
    from mac_fixture import bundle
    from harness_v6.sealed_contexts import SQLiteContextReader
    from harness_v6.ledger import ledger_from_scratch
    from harness_v6.snapshot import current_state
    from harness_v6.compact import decode_prefix
    from test_compact import equivalent
    env, b = environment('mixed_702')
    path = os.environ.get('V6_SEALED_DB')
    if not path:
        pytest.skip('Mac-only sealed G0 context absent: set V6_SEALED_DB')
    prefix = stable_prefix(snapshot_format=snapshot_format, token_counter=tiktoken_counter(), tool_descriptions=[], routing=env.manifest['routes'], machine_groups=env.manifest['machines'])
    equivalent(env.manifest['routes'], decode_prefix(prefix)['routing'])
    equivalent(env.manifest['machines'], decode_prefix(prefix)['machine_groups'])
    for entry in SQLiteContextReader(path, 'SELECT group_name,payload FROM contexts').contexts():
        ctx = entry['context']
        if entry['group'] != 'G0' or abs(ctx['time'] - 1649.82) > .01:
            continue
        ledger = ledger_from_scratch(ctx['problem'], ctx['base_plan'], {'tasks': [
            dict(task_id=t, state='running') for t in ctx['execution_state']['dispatched_task_ids']]})
        args = dict(state_version=ctx['state_revision'], running_jobs=bundle('g0_snapshot')['g0_snapshot']['running_jobs'],
                    last_cycle_receipt=None, model_notes='')
        expected = current_state(ledger, **args)
        payload = build_snapshot(prefix, ledger, snapshot_format=snapshot_format, token_counter=tiktoken_counter(), token_budget=10**9, **args)
        equivalent(expected, decode_snapshot(payload)[1])
        explicit = stable_prefix(tool_descriptions=[], routing=env.manifest['routes'], machine_groups=env.manifest['machines'])
        other = decode_snapshot(build_snapshot(explicit, ledger, token_budget=10**9, **args))
        decoded = decode_snapshot(payload)
        equivalent(other[1], decoded[1])
        for key in ('routing', 'machine_groups', 'tools'):
            equivalent(other[0][key], decoded[0][key])
        assert payload.startswith(prefix)
        assert build_snapshot(prefix, ledger, snapshot_format=snapshot_format, token_counter=tiktoken_counter(), token_budget=10**9, **args) == payload
        return
    pytest.fail('configured fixture missing G0 1649.82')
