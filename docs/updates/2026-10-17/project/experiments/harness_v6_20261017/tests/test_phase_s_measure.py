"""Synthetic tests for measurement prototypes; no physical/data dependencies."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase_s_helpers import distribution_bounds, lower_bound_walk, phase_duration, persistent_idle, slot_available
from replay_triggers import anchor_decision


def step(n,sample=100):
    return dict(step=n,family='F',sampling_percent=sample,processing=dict(type='uniform',m=10,offset=2),transport=dict(type='uniform',m=3,offset=1))


MACHINES=[dict(family='F',load=1,unload=2)]


def walk(route,**kw):
    return lower_bound_walk(route,0,now=100,first_bound=100,first_nominal=100,machines=MACHINES,**kw)


def test_minimum_and_transport_direction():
    rows=walk([step(1),step(2),step(3)])
    assert [r['earliest_start'] for r in rows]==[100,113,126]
    assert [r['nominal_start'] for r in rows]==[100,116,132]
    assert phase_duration([step(1)],0,MACHINES)==(11,13,15)


def test_skippable_still_listed_contributes_zero():
    rows=walk([step(1,50),step(2)])
    assert rows[0]['conditional'] and rows[0]['sampling_percent']==50
    assert rows[1]['earliest_start']==100 and rows[1]['nominal_start']==116
    assert walk([step(1,50),step(2)],observed_first=True)[1]['earliest_start']==113


@pytest.mark.parametrize('start,duration,expected',[(90,20,110),(0,20,100)])
def test_executing_start_and_never_before_now(start,duration,expected):
    assert walk([step(1)],executing=(start,duration))[0]['earliest_start']==expected


def test_unreleased_public_release():
    assert walk([step(1)],release=140)[0]['earliest_start']==140
    assert walk([step(1)],release=90)[0]['earliest_start']==100


def test_distribution_support():
    assert distribution_bounds(dict(type='exponential',mean=12))==(0,12,None)
    assert distribution_bounds(dict(type='constant',c=4))==(4,4,4)
    with pytest.raises(ValueError): distribution_bounds(dict(type='unknown'))


@pytest.mark.parametrize('cascade,jobs,expected',[(False,[],True),(False,[0],False),(True,[0],True),(True,[0,1],False)])
def test_slot_capacity_uses_membership_not_forecast_dates(cascade,jobs,expected):
    assert slot_available(dict(cascading=cascade,processing_until=jobs)) is expected


def test_persistence_same_machine_and_other_conditions():
    assert persistent_idle({1,2},{2,3})=={2}
    kw=dict(now=60,origin=0,delta=60,idle_machines={1},persistence=True)
    assert not anchor_decision(**kw,previous={2})['session']
    assert anchor_decision(**kw,previous={1})['session']
    assert anchor_decision(**kw,invalid_tasks=['t'])['session']
    assert anchor_decision(**kw,valid_until=119)['session']
    assert not anchor_decision(**kw,valid_until=120)['session']
    assert anchor_decision(**kw,unresolved_failure=True)['session']
    assert anchor_decision(60,0,60,idle_machines={1})['session']


def test_virtual_chain_and_public_release_window():
    from measure_physical_window import window_rows
    route=[dict(step(i),name='s'+str(i),batch_min=1,batch_max=1,setup='') for i in (1,2,3)]
    route[0]['family']='V'
    machines=[dict(id=1,family='V',group='Delay_32',load=0,unload=0),dict(id=2,family='F',group='physical',load=1,unload=2)]
    lot=dict(id='L',route='R',part='P',release=110,due=200)
    record=dict(problem=dict(time=100,operations=[]))
    rows,bounds,_,_=window_rows(record,dict(routes={'R':route},machines=machines,lots=[lot]))
    assert rows[0]['operation_id']=='L:2:1'
    assert rows[0]['earliest_start']==120  # release + virtual minimum + next transport
    assert rows[0]['readiness_basis']=='unreleased_first_step'
    assert bounds['L:3:1']==133


def test_field_variants_reconstruct_same_information():
    from measure_physical_window import field_payload, check_field_roundtrip
    route=[dict(step(1),name='op',batch_min=1,batch_max=1,setup='')]
    manifest=dict(routes={'R':route},machines=[dict(MACHINES[0],id=1)],lots=[dict(id='L',route='R')])
    op=dict(operation_id='L:1:1',lot_id='L',step=1,due=500,priority=2,waiting_since=50,eligible_machines=[1])
    current=dict(unreserved_ready=[dict(operation_id='L:1:1',eligible_machines=[1])])
    record=dict(problem=dict(operations=[op]))
    for variant in ('per_row','per_lot','route_reference'):
        payload,expected=field_payload(current,record,manifest,variant)
        check_field_roundtrip(payload,expected,variant,manifest)
    assert list(current['unreserved_ready'][0])==['operation_id','eligible_machines']


def test_preanchor_carry_requires_no_physical_transition():
    from replay_triggers import carry_is_exact
    assert carry_is_exact([])
    assert carry_is_exact([dict(kind='time_advance')])
    for kind in ('release','dispatch','operation_complete','downtime','plan_invalidated'):
        assert not carry_is_exact([dict(kind='time_advance'),dict(kind=kind)])

    from replay_triggers import public_machines_match_carry
    before=[dict(machine=1,currently_busy=False,processing_until=[])]
    after=[dict(machine=1,currently_busy=True,processing_until=[200])]
    assert public_machines_match_carry(before,after,{1:1})
    assert not public_machines_match_carry(after,before,{})  # silent process_free
    assert not public_machines_match_carry([dict(machine=1,currently_busy=True)],before,{})  # silent wake
