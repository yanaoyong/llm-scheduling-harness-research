"""Saved physical mechanism results; raw fixture data stays outside the repo."""
import json
from pathlib import Path
import pytest
from mac_fixture import bundle

@pytest.mark.parametrize('name', ['p2','e1','hour'])
def test_public_run(name):
    b=bundle('mechanism_results')
    path=Path(b['mechanism_results'][name])
    result=json.loads(path.read_text())
    assert result['recovery_equal'] and result['plan_horizon_defects']==0
    assert result['steps']>0 and result['sessions']>0
    assert result['stop']==(4302 if name=='hour' else 1603.10)
    assert all(row['tokens']>0 for row in result['rows'])
    import gzip,hashlib,itertools
    trace=json.loads(Path(str(path)+'.trace.json').read_text())
    entries=[e for e in trace if e['kind']=='ledger_snapshot']
    checkpoint=json.loads(Path(str(path)+'.checkpoint.json').read_text())
    for suffix,expected in [('.ledger.jsonl.gz',entries),('.recovery-ledger.jsonl.gz',
            [e for e in entries if e['seq']>=len(checkpoint['trace'])])]:
        with gzip.open(str(path)+suffix,'rb') as stream:
            for entry,raw in itertools.zip_longest(expected,stream):
                assert entry is not None and raw is not None
                assert hashlib.sha256(raw[:-1]).hexdigest()==entry['evidence_sha256']



def test_large_batch_reference_does_not_enumerate_losing_combinations():
    from harness_v6.audit_ledger import audit_ledger
    ops=[dict(operation_id=f'o{i:03}',eligible_machines=[1],batch_key=['x'],batch_min=25,batch_max=50) for i in range(100)]
    p=dict(time=0,machines=[dict(machine=1)],operations=ops)
    actual=audit_ledger(p)
    assert actual['avoidable_idle_matches']==[dict(machine=1,operation_ids=[f'o{i:03}' for i in range(25)])]


def test_reference_batch_choice_matches_exhaustive_oracle():
    import itertools
    from harness_v6.audit_ledger import audit_ledger
    for n in range(1,10):
        ops=[dict(operation_id=f'o{i}',eligible_machines=[1],batch_key=['x' if i%2 else 'y'],
                  batch_min=2,batch_max=3) for i in range(n)]
        candidates=sorted((json.dumps([a['batch_key'],2,3],separators=(',',':')),[a['operation_id'],b['operation_id']])
            for a,b in itertools.combinations(ops,2) if a['batch_key']==b['batch_key'])
        result=audit_ledger(dict(time=0,machines=[dict(machine=1)],operations=ops))
        assert result['avoidable_idle_matches']==([dict(machine=1,operation_ids=candidates[0][1])] if candidates else [])


def test_route_cache_preserves_float_order_and_bindings():
    from types import SimpleNamespace
    from harness_v6.observation import _route_tables
    class Env: pass
    env=Env()
    steps=[SimpleNamespace(order=i+1,processing_time={'c':x},lot_to_lens_dedication=(3 if i==0 else None))
        for i,x in enumerate([1.,1e16,1.,-1e16])]
    env.routes={'r':SimpleNamespace(steps=steps)}
    table=_route_tables(env)
    for i,s in enumerate(steps):
        assert table['r'][i]==(sum(x.processing_time['c'] for x in steps[i+1:]),
                              [x for x in steps[:i] if x.lot_to_lens_dedication==s.order])
    assert _route_tables(env) is table


def test_expired_conditional_hold_does_not_require_anchor_physical_validator():
    from harness_v6.env_adapter import FullFabEnvironment
    env=FullFabEnvironment.__new__(FullFabEnvironment)
    env.t=10;env.horizon=100;env.physical={1};env.plan=None;env.plan_versions=set()
    env.invalidated_task_ids=set();env.decisions=0
    env._emit=lambda *a,**kw: None
    plan=dict(version='p',created_at=10,freeze_until=10,valid_until=100,scope=[1],reason='test',tasks=[],
        holds=[dict(machine=1,until=9,reason='expired',after_task_id='gone')])
    env.commit_plan(plan)
    assert env.plan==plan
    live={**plan,'version':'next','holds':[{**plan['holds'][0],'until':11}]}
    with pytest.raises(ValueError,match='conditional hold'):env.commit_plan(live)
    from harness_v6.audit_v6 import audit_plan_sources
    manifest=dict(machines=[dict(id=1,group='production')],lots=[],controlled_machine_ids=[1],horizon=100)
    trace=[dict(seq=0,time=0,kind='initial',manifest=manifest),dict(seq=1,time=10,kind='plan_committed',plan=plan)]
    assert audit_plan_sources(trace)['valid']
    trace[1]['plan']=live
    assert not audit_plan_sources(trace)['valid']


@pytest.mark.parametrize('state',[None,'running','done','invalid'])
def test_ephemeral_view_matches_detached_ledger_without_changing_input(state):
    from copy import deepcopy
    from harness_v6.ledger import ledger_from_scratch,ledger_read_view
    from test_ledger import fixture,task
    p,plan=fixture();plan['tasks']=[task()];before=deepcopy((p,plan))
    receipts={'tasks':[] if state is None else [{'task_id':'t','state':state}]}
    view=ledger_read_view(p,plan,receipts);detached=ledger_from_scratch(p,plan,receipts)
    assert view.rows()==detached.rows() and view.metrics()==detached.metrics()
    assert view.pending_tasks()==detached.pending_tasks()
    assert (p,plan)==before


def test_frozen_observation_default_lower_bound_without_physics():
    from harness_v6.observation import build_problem
    from copy import deepcopy
    class Env: pass
    env=Env();env.t=10;env.trace=[];env.routes={};env.jobs={};env.pm_counters={};env.physical=set();env.lots={}
    env.executed_tasks=set();env.manifest={'setups':[]};env.min_runs={}
    env.plan=dict(version='v',created_at=9,freeze_until=20,tasks=[dict(id='t',lot_ids=['l'],steps=[1],visits=[1])])
    before=deepcopy(env.plan)
    p=build_problem(env)
    assert p['frozen_tasks'][0]['original_not_before']==9 and p['frozen_tasks'][0]['start']==10
    assert env.plan==before


def test_physical_receipt_projection_has_deterministic_order():
    from harness_v6.env_adapter import FullFabEnvironment
    env=FullFabEnvironment.__new__(FullFabEnvironment)
    env.plan={'version':'v','created_at':0,'tasks':[]}
    env.executed_tasks={('v','z'),('v','a'),('old','x')};env.invalidated_task_ids={'q','b'}
    env.problem=lambda:dict(time=0,machines=[],operations=[])
    assert env.ledger_snapshot()['receipts']['tasks']==[
        dict(task_id='a',state='done'),dict(task_id='z',state='done'),
        dict(task_id='b',state='invalid'),dict(task_id='q',state='invalid')]


def test_indexed_matching_matches_naive_cross_machine_enumeration():
    import itertools,random
    from harness_v6.ledger import ledger_from_scratch
    from harness_v6.audit_ledger import audit_ledger
    rng=random.Random(17)
    for _ in range(100):
        ops=[dict(operation_id=f'o{i}',eligible_machines=[rng.randrange(4) for _ in range(3)],
            batch_key=[str(rng.randrange(2))],batch_min=2,batch_max=3) for i in range(9)]
        machines=[dict(machine=i,currently_busy=(rng.random()<0.2)) for i in range(4)]
        used=set();expected=[]
        for m in machines:
            if m['currently_busy']:continue
            eligible=[o for o in ops if o['operation_id'] not in used and m['machine'] in o['eligible_machines']]
            batches=sorted((json.dumps([a['batch_key'],2,3],separators=(',',':')),[a['operation_id'],b['operation_id']])
                for a,b in itertools.combinations(eligible,2) if a['batch_key']==b['batch_key'])
            if batches:
                ids=batches[0][1];used.update(ids);expected.append(dict(machine=m['machine'],operation_ids=ids))
        problem=dict(time=0,machines=machines,operations=ops)
        assert ledger_from_scratch(problem).metrics()['avoidable_idle_matches']==expected
        assert audit_ledger(problem)['avoidable_idle_matches']==expected
