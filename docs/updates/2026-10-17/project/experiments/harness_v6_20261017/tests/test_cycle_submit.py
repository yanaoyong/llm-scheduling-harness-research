from copy import deepcopy
import pytest
from harness_v6.cycle import CycleMachine, CycleConfig, next_anchor, DriftRule, DriftMonitor
from harness_v6.submit import Submitter
from harness_v6.synthetic import SyntheticFactory, scripted_delta, SOURCE


def submitter(f=None, **kwargs):
    f=f or SyntheticFactory()
    return Submitter(f.plan,f.problem(),f.execution_state(),state_version=1,next_anchor=60,source_sha256=SOURCE,**kwargs)


def test_config_and_anchor():
    assert next_anchor(702,702,60)==762
    assert next_anchor(762,702,60)==822
    assert CycleConfig.for_stage('S1',delta=900).horizon==2700
    assert CycleConfig.for_stage('S2',delta=300).breakdowns
    with pytest.raises(ValueError):CycleConfig.for_stage('S1')
    with pytest.raises(ValueError):CycleConfig(delta=0)


def test_session_counts():
    c=CycleMachine();assert not c.begin(0,valid_until=900)['session']
    c.begin(60,avoidable_idle=1,valid_until=900);c.finish(submitted=True,model_note='x')
    c.begin(70,event='expired_task',valid_until=900);c.finish(submitted=True)
    assert not c.begin(120,valid_until=900)['session']
    assert (c.sessions,c.interrupts,c.empty_cycles)==(2,1,2)


@pytest.mark.parametrize('time,anchor,merged',[(89,120,None),(90,120,None),(91,180,120)])
def test_merge(time,anchor,merged):
    c=CycleMachine();c.begin(0,valid_until=900);c.begin(60,valid_until=900)
    c.begin(time,event='plan_invalidated',valid_until=900);r=c.finish(submitted=True)
    assert c.anchor==anchor and r['merged_anchor']==merged


@pytest.mark.parametrize('kw',[dict(avoidable_idle=1),dict(invalid_tasks=['x']),dict(valid_until=59)])
def test_predicates(kw):
    assert CycleMachine().begin(0,**{'valid_until':900,**kw})['session']


def test_failures_and_unknown_cap():
    c=CycleMachine()
    c.begin(0,avoidable_idle=1,valid_until=900);c.finish(submitted=True,process_ok=False,cost=3,wall_seconds=7)
    assert c.unresolved_failure and c.anchor==60
    assert c.begin(60,valid_until=900)['session']
    c.finish(submitted=False,cost=4,wall_seconds=8)
    assert c.stop_reason=='consecutive_failures' and c.cost==7 and c.wall_seconds==15
    c=CycleMachine(config=CycleConfig(k_fail=5,unknown_usage_cap=2))
    for i,known in enumerate([False,True,False]):
        c.begin(i*60,avoidable_idle=1,valid_until=900);c.finish(submitted=True,usage_known=known,model_note='x')
    assert c.stop_reason=='unknown_usage_cap'


@pytest.mark.parametrize('success',[True,False])
def test_stall(success):
    c=CycleMachine(config=CycleConfig(k_fail=9,stall_cycles=3))
    for i in range(3):
        c.begin(i*60,avoidable_idle=1,valid_until=900);c.finish(submitted=success)
    assert c.stop_reason=='stall'


def test_note_and_improvement():
    c=CycleMachine(config=CycleConfig(stall_cycles=2))
    for i,idle in enumerate([3,2,1,1,1]):
        c.begin(i*60,avoidable_idle=idle,valid_until=900)
        c.finish(submitted=True,model_note='explicit explanation' if i>=3 else '')
    assert c.stop_reason is None


def test_interrupt_filter_defect_terminal():
    c=CycleMachine();c.begin(0,valid_until=900)
    assert not c.begin(10,event='no_plan',avoidable_idle=1,valid_until=900)['session']
    assert not c.begin(11,event='no_plan',avoidable_idle=0)['session']
    assert not c.begin(12,event='breakdown',invalid_tasks=['a'])['session']
    assert c.begin(13,event='plan_horizon')['kind']=='defect' and c.sessions==0
    c=CycleMachine(config=CycleConfig(breakdowns=True));c.begin(0,valid_until=900)
    assert c.begin(10,event='breakdown',invalid_tasks=['a'])['event']=='plan_invalidated'
    c.finish(submitted=True);c.begin(20,event='terminal');c.finish(submitted=True)
    assert c.stop_reason=='terminal'


def test_submit_atomic_idempotent_closed():
    f=SyntheticFactory();s=submitter(f);d=scripted_delta(f,1)
    r=s.submit_plan(1,'id',d);assert r['accepted'] and r['coverage']['report_only']
    assert s.submit_plan(1,'id',d)==r
    assert s.submit_plan(1,'other',d)['violations'][0]['code']=='cycle_closed'
    changed=deepcopy(d);changed['plan_header']['reason']='different'
    assert s.submit_plan(1,'id',changed)['violations'][0]['code']=='submission_id_conflict'
    assert s.finalize(process_ok=False)==f.plan and not s.adopted
    assert s.finalize(process_ok=True)==f.plan


def test_empty_and_absent_submission():
    f=SyntheticFactory();f.plan['valid_until']=900;s=submitter(f)
    r=s.submit_plan(1,'noop',{});assert r['accepted'] and r['no_change']
    assert len(r['coverage']['uncovered_operation_ids'])==4
    assert s.finalize(process_ok=True)==f.plan and s.adopted
    absent=submitter(f);assert absent.finalize(process_ok=True)==f.plan and not absent.adopted


def test_lower_bound_stale_collecting_precheck():
    f=SyntheticFactory();s=submitter(f);d=scripted_delta(f,1);d['plan_header']['valid_until']=119
    assert 'valid_until_lower_bound' in [e['code'] for e in s.submit_plan(1,'short',d)['violations']]
    d['plan_header']['valid_until']=120
    assert s.submit_plan(0,'stale',d)['violations'][0]['code']=='stale_state_version'
    assert s.submit_plan(1,'ok',d)['accepted']
    assert s.finalize(process_ok=True)['valid_until']==120
    s=submitter(f,physical_precheck=lambda *args:[{'code':'physics','detail':'failure'}])
    d['plan_header']['valid_until']=119
    assert [e['code'] for e in s.submit_plan(1,'x',d)['violations']]==['valid_until_lower_bound','physics']


def test_implicit_retention_and_detachment():
    f=SyntheticFactory();d=scripted_delta(f,1)
    s=submitter(f);r=s.submit_plan(1,'x',d);assert r['accepted']
    r['coverage']['uncovered_operation_ids'].append('tamper')
    assert 'tamper' not in s.submit_plan(1,'x',d)['coverage']['uncovered_operation_ids']


def test_drift():
    d=DriftMonitor(DriftRule({'input_per_request':100},2))
    assert not d.observe(0,{'input_per_request':200})
    assert not d.observe(1,{'input_per_request':50})
    assert not d.observe(2,{'input_per_request':200})
    assert d.observe(3,{'input_per_request':200})
    with pytest.raises(ValueError):d.observe(3,{'input_per_request':200})


def test_absent_plan_without_idle_is_empty_and_empty_resets_idle_streak():
    c=CycleMachine(config=CycleConfig(stall_cycles=2))
    assert not c.begin(0,valid_until=None)['session']
    c.begin(60,avoidable_idle=1,valid_until=900);c.finish(submitted=True)
    c.begin(120,valid_until=900)
    c.begin(180,avoidable_idle=1,valid_until=900);c.finish(submitted=True)
    assert c.stop_reason is None
    assert CycleConfig(delta=900).horizon==2700


def test_failure_counter_resets_on_success_and_hourly_budget_gate():
    c=CycleMachine(config=CycleConfig(segment_cycles=1000,hourly_cost_cap=1))
    c.begin(0,avoidable_idle=1);c.finish(submitted=False,cost=2)
    c.begin(60,valid_until=900);c.finish(submitted=True,model_note='x')
    assert c.failures==0 and c.cost==2
    for time in range(120,3601,60):c.begin(time,valid_until=9000)
    assert c.stop_reason=='budget_cap' and c.last_record['segment_boundary']


def test_merged_anchor_is_visible_to_submit_precheck():
    c=CycleMachine();c.begin(0,valid_until=900);c.begin(60,valid_until=900)
    r=c.begin(91,event='expired_task',valid_until=900)
    assert r['next_anchor']==c.anchor==180
    f=SyntheticFactory();f.now=91
    s=Submitter(f.plan,f.problem(),f.execution_state(),state_version=1,next_anchor=c.anchor,source_sha256=SOURCE)
    d=scripted_delta(f,1);d['plan_header']['valid_until']=180
    assert not s.submit_plan(1,'short',d)['accepted']
    d['plan_header']['valid_until']=240
    assert s.submit_plan(1,'ok',d)['accepted']
    c.finish(submitted=True)
    assert c.anchor==180


@pytest.mark.parametrize('key,value', [('input_per_request',200),('requests',200),('submit_rejection_rate',.9),('avoidable_idle',3)])
def test_all_drift_signals(key,value):
    d=DriftMonitor(DriftRule({key:value/2},2))
    assert not d.observe(0,{key:value})
    assert d.observe(1,{key:value})
