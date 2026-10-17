"""Additional sealed acceptance assertions; absent evidence is explicitly skipped."""
import json
import os
from pathlib import Path
import pytest
from mac_fixture import environment, bundle
from harness_v6.contracts import digest


def test_mixed_roundtrip():
    env,b=environment('mixed_702')
    from harness_v6.factory_v6 import capture,restore
    state=capture(env)
    assert state['t']==702 and 'batch_state' not in state
    assert digest(capture(restore(state,env.trace,data_dir=b['data_dir'])))==digest(state)


def test_d34_original_pending_tasks():
    env,b=environment('d34_421')
    plan=b['d34_421']['plan']
    executed={tid for version,tid in env.executed_tasks if version==env.plan['version']}
    assert plan['tasks']==[t for t in env.plan['tasks'] if t['id'] not in executed]
    task=next(t for t in plan['tasks'] if t['id']=='d34-421')
    assert task['not_before']<env.t
    env.commit_plan(plan)
    assert next(t for t in env.plan['tasks'] if t['id']=='d34-421')==task


def test_w1462_and_common_endpoint():
    b=bundle('w1462_case')
    path=os.environ.get('V6_SEALED_DB');query=os.environ.get('V6_SEALED_SELECT')
    if not path or not query:pytest.skip('sealed evidence not provided')
    from harness_v6.sealed_contexts import SQLiteContextReader
    from harness_v6.ledger import ledger_from_scratch
    refs={c['context_ref'] for c in b['w1462_case']['calls']}
    found=False; endpoints={}
    for entry in SQLiteContextReader(path,query).contexts():
        ctx=entry['context']
        if ctx['context_ref'] in refs:
            receipts={'tasks':[{'task_id':t,'state':'running'} for t in ctx['execution_state']['dispatched_task_ids']]}
            ledger=ledger_from_scratch(ctx['problem'],ctx['base_plan'],receipts)
            assert ledger.metrics()['avoidable_idle']==0
            assert ledger.rows()['w1462:131:1']['state']=='reserved_not_started'
            found=True
        if ctx.get('measurement')=='common_endpoint':
            metrics=ledger_from_scratch(ctx['problem'],ctx['base_plan'],ctx['ledger_receipts']).metrics()
            endpoints[entry['group']]=any('w1703:86:1' in match['operation_ids']
                for key in ('avoidable_idle_matches','explicit_wait_idle_matches') for match in metrics[key])
    assert found
    assert set(endpoints)=={'G0','G1','G2'}
    assert any(endpoints.values()),endpoints
