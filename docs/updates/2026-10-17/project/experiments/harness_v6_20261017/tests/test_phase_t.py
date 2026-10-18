"""Phase T public presentation contracts; no data, simulator or model required."""
from copy import deepcopy
import hashlib
from pathlib import Path
import pytest
from harness_v6.physical_window import lower_bound_walk, public_operation, queue_diagnostics
from harness_v6.ledger import ledger_from_scratch, idle, eligible
from harness_v6.facts import FactReader, build_facts
from harness_v6.contracts import HarnessError
from harness_v6.cycle import CycleMachine
from harness_v6.snapshot import current_state, stable_prefix, build_snapshot
from harness_v6.compact import decode_snapshot, normalize
from test_ledger import fixture, op, task
from test_phase_s_measure import step, MACHINES


def test_production_lower_bound_sampling_transport_release_execution():
    rows=lower_bound_walk([step(1,50),step(2),step(3)],0,now=100,first_bound=100,
        first_nominal=100,machines=MACHINES,executing=(90,25),release=110)
    assert [r['earliest_start'] for r in rows]==[115,115,128]
    assert rows[0]['conditional']
    assert [r['nominal_start'] for r in rows]==[110,126,142]


@pytest.mark.parametrize('cascading,jobs,expected',[(False,[],True),(False,[0],False),(True,[0],True),(True,[0,1],False)])
def test_idle_uses_observed_slots(cascading,jobs,expected):
    assert idle(dict(cascading=cascading,processing_until=jobs),100)==expected


def test_qualification_and_no_arrival_placeholder():
    o=dict(op('a'),qualification_uncertain=True,conditional=True,predecessor_ids=['p'],release_time=100)
    row=public_operation(o,100)
    assert 'release_time' not in row and 'waiting_since' not in row
    assert 'qualification_uncertain' not in row
    assert row['qualification_basis']=='no recorded dedication; simulator does not restrict'
    assert eligible(o,dict(machine=1))
    assert not eligible(dict(o,same_machine_as='p'),dict(machine=1))


def test_range_filters_coverage_complete_version_bound():
    p,plan=fixture();p['operations']=[dict(op(str(i)),earliest_start=i,nominal_start=i) for i in range(1103)]
    p['operations'] += [dict(op('null'),earliest_start=None),op('absent')]
    reader=FactReader('v1',build_facts(p,plan))
    where=[dict(field='earliest_start',op='gte',value=100),dict(field='earliest_start',op='lt',value=1000)]
    query=dict(kind='operations',cursor=None,count=77,where=where);found=[]
    while True:
        result=reader.read(query);found += [e['id'] for e in result['entities']]
        if result['next_cursor'] is None:break
        query['cursor']=result['next_cursor']
    assert found==[str(i) for i in range(100,1000)]
    with pytest.raises(HarnessError,match='stale_cursor'):
        FactReader('v2',reader.facts).read(query)
    for value in (True,None,float('inf'),float('nan')):
        with pytest.raises(HarnessError,match='query_filter'):
            reader.read(dict(kind='operations',cursor=None,count=1,where=[dict(field='earliest_start',op='gt',value=value)]))
    query=dict(kind='operations',cursor=None,count=512,where=[dict(field='coverage_uncovered',op='eq',value=True)])
    ids=[]
    while True:
        page=reader.read(query); ids += [e['id'] for e in page['entities']]
        if page['next_cursor'] is None:break
        query['cursor']=page['next_cursor']
    assert len(ids)==1105 and len(set(ids))==1105


@pytest.mark.parametrize('fmt',['explicit','dense'])
def test_diagnostics_fields_roundtrip_do_not_mutate_or_interrupt(fmt):
    p,plan=fixture();p['operations']=[dict(op('a'),conditional=True,earliest_start=30,nominal_start=1000,
        priority=2,processing_seconds_min=5,processing_seconds_max=None,readiness_basis='exported_predecessor',sampling_percent=50)]
    plan['tasks']=[dict(task('gone'),machine=1)]
    ledger=ledger_from_scratch(p,plan);before=deepcopy(ledger)
    diagnostics=queue_diagnostics(ledger)
    assert diagnostics['blocked_queues']==[dict(machine=1,task_id=plan['tasks'][0]['id'],reason='invalid task')]
    assert diagnostics['absent_operation_tasks'][0]['operation_ids']==['gone']
    args=dict(horizon_seconds=60,state_version=1,running_jobs=[],last_cycle_receipt=None,model_notes='')
    current=current_state(ledger,**args)
    assert current['upcoming_operations'][0]['nominal_start']==1000  # mean never filters
    prefix=stable_prefix(tool_descriptions=[],routing={},machine_groups=[],snapshot_format=fmt,setup_transitions={'A':1},min_runs={'A':2})
    pref,decoded=decode_snapshot(build_snapshot(prefix,ledger,token_budget=10**8,snapshot_format=fmt,**args))
    assert decoded==normalize(current) and pref['min_runs']=={'A':2}
    assert ledger==before
    assert CycleMachine().begin(0,avoidable_idle=0,valid_until=900)['session'] is False


def test_cycle_decisions_same_for_identical_inputs():
    # Pin the actual pre-T implementation, in addition to behavioral checks.
    path=Path(__file__).parents[1]/'src/harness_v6/cycle.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='2ad7002dcef8d826ca9c7b61d1577085894a371ab2e4466cada2f57575444972'
    for event in (None,'plan_invalidated','expired_task','no_plan','terminal'):
        for idle_count in (0,1):
            a,b=CycleMachine(),CycleMachine()
            kwargs=dict(avoidable_idle=idle_count,valid_until=900,event=event)
            assert a.begin(0,**kwargs)==b.begin(0,**kwargs)


def test_live_export_window_union_and_unreleased():
    from types import SimpleNamespace as N
    from harness_v6.observation import build_problem
    class Env: pass
    env=Env(); env.t=0; env.trace=[]; env.jobs={}; env.pm_counters={}; env.processing_by_machine={}
    env.plan=None;env.physical={1};env.family_machines={'F':[1]};env.min_runs={}
    env.machine_state={1:dict(ready=0,down_until=0,setup='',min_left=0,min_setup='')}
    env.machines={1:N(family='F',load_time=1,unload_time=2,cascading=False)}
    steps=[N(order=i,processing_time={'c':100},transport_time=None,cascading_time={'c':100},
             family='F',lot_to_lens_dedication=None,sampling_percent=100,rework_percent=0,
             step_name='s',batch_min=1,batch_max=1,setup_needed='',setup_time=0) for i in range(1,6)]
    env.routes={'R':N(steps=steps)}
    env.lots={lid:dict(status=status,step=0,route='R',dedications={},visits={'1':1} if status=='waiting' else {},
             part='P',priority=1,due=500,ready_since=0) for lid,status in [('a','waiting'),('b','unreleased'),('c','unreleased')]}
    env.manifest=dict(routes={'R':[dict(step=i,family='F',processing={'type':'constant','c':100},
        transport={'type':'constant','c':0},sampling_percent=100) for i in range(1,6)]},
        machines=[dict(id=1,family='F',load=1,unload=2)],setups=[],
        lots=[dict(id='a',release=0),dict(id='b',release=20),dict(id='c',release=1000)])
    short=build_problem(env,horizon_seconds=50,lookahead_depth=2)
    assert [o['step'] for o in short['operations'] if o['lot_id']=='a']==[1,2]
    wide=build_problem(env,horizon_seconds=250,lookahead_depth=2)
    assert [o['step'] for o in wide['operations'] if o['lot_id']=='a']==[1,2,3]
    assert {o['operation_id'] for o in short['operations']} <= {o['operation_id'] for o in wide['operations']}
    assert all(o['lot_id']!='c' for o in wide['operations'])
    assert next(o for o in wide['operations'] if o['lot_id']=='b')['earliest_start']==20
    assert all(o['processing_seconds_min']==103==o['processing_seconds_max'] for o in wide['operations'])


def test_due_dedicated_map_disabled_above_cap():
    from harness_v6.snapshot import INCLUDE_DUE,due_values
    assert INCLUDE_DUE is False  # measured G0 dense increment 10,676 > 8,000
    p,plan=fixture();p['operations']=[dict(op('a'),due=300),dict(op('b'),due=400)]
    assert due_values(ledger_from_scratch(p,plan),{'unreserved_ready':[{'operation_id':'a'}],'upcoming_operations':[]})=={'a':300}


def test_candidate_coverage_changes_invalidate_pages():
    p,plan=fixture();p['operations']=[op(str(i)) for i in range(100)]
    reader=FactReader('v',build_facts(p,plan))
    query=dict(kind='operations',cursor=None,count=10,where=[dict(field='coverage_uncovered',op='eq',value=True)])
    first=reader.read(query)
    reader.set_coverage_plan(dict(plan,tasks=[task('0')]))
    assert reader.read(query)['matching_total']==99
    with pytest.raises(HarnessError,match='stale_cursor'):
        reader.read(dict(query,cursor=first['next_cursor']))


def test_frozen_inventory_only_and_public_times():
    from harness_v6.physical_window import frozen_operations
    p,plan=fixture();p['operations']=[dict(op('a'),step=1,lot_id='a',visit=1,readiness_basis='observed_ready',priority=1,due=100,waiting_since=1),
        dict(op('a:2'),step=2,lot_id='a',visit=1,readiness_basis='exported_predecessor',conditional=True,predecessor_ids=['a'])]
    manifest=dict(lots=[dict(id='a',route='R',release=0)],routes={'R':[step(1),step(2),step(3)]},machines=[dict(MACHINES[0],id=1)])
    before=deepcopy(p);new=frozen_operations(p,manifest)
    assert p==before
    assert [o['operation_id'] for o in new['operations']]==['a','a:2']
    assert [o['earliest_start'] for o in new['operations']]==[10,23]
    assert [o['nominal_start'] for o in new['operations']]==[10,26]
    reader=FactReader('v',build_facts(new,plan));row=reader.read(dict(kind='operations',ids=['a:2']))['entities'][0]['value']
    assert 'release_time' not in row and row['earliest_start']==23


def test_empty_coverage_query_is_complete():
    reader=FactReader('empty',build_facts(dict(time=0,machines=[],operations=[]),dict(tasks=[],holds=[])))
    page=reader.read(dict(kind='operations',cursor=None,count=512,where=[dict(field='coverage_uncovered',op='eq',value=True)]))
    assert page['matching_total']==0 and page['entities']==[] and page['next_cursor'] is None


def test_public_lower_bound_never_before_current_clock():
    assert public_operation(dict(op('a'),earliest_start=5),100)['earliest_start']==100


def test_legacy_unfinished_predecessor_placeholder_is_not_a_nominal_forecast():
    raw=dict(op('future'),predecessor_ids=['unfinished'],release_time=100)
    public=public_operation(raw,100)
    assert 'release_time' not in public and public['nominal_start'] is None
    assert public['earliest_start']==100  # weak physical bound, never an arrival claim
